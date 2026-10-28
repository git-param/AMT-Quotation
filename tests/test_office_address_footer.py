"""Three-office footer rendering shared by the normal and bulk PI exports."""
from io import BytesIO
import unittest

from PIL import Image as PILImage

from backend.orders.normal_pi.exports import (
    OfficeAddressTable,
    OfficeLocationPin,
    office_address_pdf,
    office_address_png,
)


class OfficeAddressFooterTests(unittest.TestCase):
    def setUp(self):
        self.addresses = [
            'Plot 1149, Vinay Villa,\nSir P Pattani Road, Krishna Nagar,\nBhavnagar-364001.',
            '106 - 107, Patel Avenue, S.G.Highway,\nNr. Gurudwara, Bodakdev,\nAhmedabad, Gujarat-380054.',
            '257 Paiki 2/1, 258 Paiki 2/2,\nNr. Nandani Hotel, Tansa,\nDist-Ghogha, Bhavnagar-364120.',
        ]

    def test_pdf_strip_has_even_address_centers_and_vector_pins(self):
        table = office_address_pdf(self.addresses, 600)
        self.assertEqual(table.wrap(600, 500)[0], 600)
        self.assertEqual(table._colWidths, [150, 75, 150, 75, 150])
        self.assertIsInstance(table, OfficeAddressTable)
        self.assertEqual(table.divider_height, 30)
        self.assertEqual(table.hAlign, 'LEFT')
        self.assertEqual(table._linecmds, [])
        self.assertEqual(table._colpositions[1:-1], [150, 225, 375, 450])
        self.assertEqual(len(table._cellvalues[0]), 5)
        for cell in (table._cellvalues[0][0],table._cellvalues[0][2],table._cellvalues[0][4]):
            self.assertIsInstance(cell[0], OfficeLocationPin)
            self.assertEqual((cell[0].width, cell[0].height), (20.25, 23.25))

    def test_excel_default_footer_uses_address_asset_at_even_reference_spacing(self):
        image_data = office_address_png(self.addresses, 600)
        with PILImage.open(BytesIO(image_data.getvalue())) as strip:
            self.assertEqual(strip.size, (1200, 120))
            pixels = strip.load()
            for y, centers in ((50, (373, 820)), (60, (373, 820)), (70, (373, 820))):
                for center in centers:
                    self.assertTrue(any(pixels[x,y][0]>80 and pixels[x,y][0]>pixels[x,y][1]*1.5
                                        for x in range(center-2,center+3)))
            self.assertEqual(pixels[0, 60], (255,255,255,255))
            self.assertEqual(pixels[1199, 60], (255,255,255,255))

    def test_excel_custom_addresses_remain_configurable(self):
        custom=['North office','Central office','South office']
        image_data=office_address_png(custom,600)
        with PILImage.open(BytesIO(image_data.getvalue())) as strip:
            self.assertEqual(strip.size,(1200,280))
            pixels=strip.load();red=(133,32,32)
            for y,centers in ((118,(375,825)),(158,(375,825)),(198,(375,825))):
                for center in centers:
                    self.assertIn(red,[pixels[x,y] for x in range(center-3,center+4)])


if __name__ == '__main__':
    unittest.main()
